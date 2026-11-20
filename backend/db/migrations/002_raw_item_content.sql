-- Bytes of RawItems that arrive through the API (fallback upload). Connectors keep theirs on the shared volume
-- (raw_item.storage_uri); /raw-items/{id}/content serves from here first.
create table raw_item_content (
  raw_item_id  text primary key references raw_items(id) on delete cascade,
  content_type text not null,
  bytes        bytea not null
);
