import datetime
import ipaddress
import json
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import openai
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from backend import settings
from backend.agents.llm import default_client
from backend.api.routes.system import _llm_reachable

TOKEN = "test-token"
MODELS = {"object": "list", "data": [{"id": "gpt-oss-20b", "object": "model", "created": 0, "owned_by": "vllm"}]}


def _name(common_name):
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])


def _certificate(subject, issuer, public_key, signing_key, *, ca, names=()):
    now = datetime.datetime.now(datetime.timezone.utc)
    builder = (x509.CertificateBuilder().subject_name(subject).issuer_name(issuer).public_key(public_key)
               .serial_number(x509.random_serial_number())
               .not_valid_before(now - datetime.timedelta(minutes=5))
               .not_valid_after(now + datetime.timedelta(days=1))
               .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True))
    if names:
        builder = builder.add_extension(x509.SubjectAlternativeName(list(names)), critical=False)
    return builder.sign(signing_key, hashes.SHA256())


def _pem(certificate):
    return certificate.public_bytes(serialization.Encoding.PEM)


class _Models(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/v1/models" or self.headers.get("Authorization") != f"Bearer {TOKEN}":
            self.send_response(401)
            self.end_headers()
            return
        body = json.dumps(MODELS).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def tls_model(tmp_path, monkeypatch):
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca = _certificate(_name("SAMPLE test service CA"), _name("SAMPLE test service CA"), ca_key.public_key(),
                      ca_key, ca=True)
    server_key = ec.generate_private_key(ec.SECP256R1())
    server = _certificate(_name("localhost"), ca.subject, server_key.public_key(), ca_key, ca=False,
                          names=[x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))])
    ca_file = tmp_path / "service-ca.crt"
    ca_file.write_bytes(_pem(ca))
    chain_file = tmp_path / "server.pem"
    chain_file.write_bytes(_pem(server) + server_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(chain_file)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Models)
    httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    base_url = f"https://localhost:{httpd.server_address[1]}/v1"
    monkeypatch.setenv("ORDO_LLM_ENABLED", "1")
    monkeypatch.setenv("ORDO_LLM_BASE_URL", base_url)
    monkeypatch.setenv("ORDO_LLM_API_KEY", TOKEN)
    monkeypatch.delenv("ORDO_LLM_CA_FILE", raising=False)
    monkeypatch.setattr(settings, "SERVICE_CA_FILE", str(tmp_path / "absent.crt"))
    yield base_url, ca_file
    httpd.shutdown()
    httpd.server_close()


def test_model_client_trusts_the_ca_named_in_the_environment(tls_model, monkeypatch):
    _, ca_file = tls_model
    monkeypatch.setenv("ORDO_LLM_CA_FILE", str(ca_file))

    assert [m.id for m in default_client().models.list()] == ["gpt-oss-20b"]


def test_model_client_trusts_the_pod_service_ca_by_default(tls_model, monkeypatch):
    _, ca_file = tls_model
    monkeypatch.setattr(settings, "SERVICE_CA_FILE", str(ca_file))

    assert [m.id for m in default_client().models.list()] == ["gpt-oss-20b"]


def test_health_probe_trusts_the_service_ca(tls_model, monkeypatch):
    base_url, ca_file = tls_model
    monkeypatch.setattr(settings, "SERVICE_CA_FILE", str(ca_file))

    assert _llm_reachable(base_url) is True


def test_without_the_service_ca_the_model_is_not_trusted(tls_model):
    base_url, _ = tls_model

    with pytest.raises(openai.APIConnectionError):
        default_client().models.list()
    assert _llm_reachable(base_url) is False
