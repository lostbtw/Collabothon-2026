FROM registry.access.redhat.com/ubi9/python-312

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /opt/app-root/src

COPY --chown=1001:0 sim/bank/requirements.txt ./sim/bank/requirements.txt
RUN pip install -r sim/bank/requirements.txt

COPY --chown=1001:0 sim ./sim

WORKDIR /opt/app-root/src/sim/bank

EXPOSE 8081
CMD ["uvicorn", "bank_sim.app:app", "--host", "0.0.0.0", "--port", "8081"]
