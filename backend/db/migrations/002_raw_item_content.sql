create table raw_item_content (
  raw_item_id  text primary key references raw_items(id) on delete cascade,
  content_type text not null,
  bytes        bytea not null
);
