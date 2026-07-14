-- Built-in non-workforce actors whose actions require durable attribution.
CREATE TABLE system_principal (
    id           TEXT PRIMARY KEY,
    kind         TEXT NOT NULL,
    display_name TEXT NOT NULL,
    purpose      TEXT NOT NULL,
    created_at   TEXT NOT NULL
);