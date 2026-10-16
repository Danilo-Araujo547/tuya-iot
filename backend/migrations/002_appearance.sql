CREATE TABLE wallpapers (
    id VARCHAR PRIMARY KEY,
    name VARCHAR NOT NULL,
    image BYTEA NOT NULL,
    created DOUBLE PRECISION NOT NULL
);
CREATE TABLE appearance (
    id VARCHAR PRIMARY KEY,
    selected VARCHAR NOT NULL
);
INSERT INTO appearance (id, selected) VALUES ('dashboard', 'solar');
