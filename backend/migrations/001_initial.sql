
CREATE TABLE api_keys (
	hash VARCHAR NOT NULL, 
	name VARCHAR NOT NULL, 
	control BOOLEAN NOT NULL, 
	PRIMARY KEY (hash), 
	UNIQUE (name)
)

;


CREATE TABLE commands (
	id VARCHAR NOT NULL, 
	device_id VARCHAR NOT NULL, 
	actor VARCHAR NOT NULL, 
	key VARCHAR NOT NULL, 
	power BOOLEAN NOT NULL, 
	status VARCHAR NOT NULL, 
	response JSON, 
	created FLOAT NOT NULL, 
	updated FLOAT NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (actor, key)
)

;


CREATE TABLE devices (
	id VARCHAR NOT NULL, 
	name VARCHAR NOT NULL, 
	config JSON NOT NULL, 
	PRIMARY KEY (id)
)

;


CREATE TABLE events (
	id VARCHAR NOT NULL, 
	payload JSON NOT NULL, 
	received FLOAT NOT NULL, 
	payload_pruned BOOLEAN NOT NULL, 
	status VARCHAR NOT NULL, 
	attempts INTEGER NOT NULL, 
	next_attempt FLOAT NOT NULL, 
	error VARCHAR, 
	PRIMARY KEY (id)
)

;


CREATE TABLE health (
	name VARCHAR NOT NULL, 
	value JSON NOT NULL, 
	updated FLOAT NOT NULL, 
	PRIMARY KEY (name)
)

;


CREATE TABLE measurements (
	id VARCHAR NOT NULL, 
	event_id VARCHAR NOT NULL, 
	device_id VARCHAR NOT NULL, 
	property VARCHAR NOT NULL, 
	value JSON NOT NULL, 
	unit VARCHAR NOT NULL, 
	observed FLOAT NOT NULL, 
	received FLOAT NOT NULL, 
	PRIMARY KEY (id)
)

;


CREATE TABLE rates (
	key VARCHAR NOT NULL, 
	"window" INTEGER NOT NULL, 
	count INTEGER NOT NULL, 
	PRIMARY KEY (key)
)

;


CREATE TABLE sessions (
	hash VARCHAR NOT NULL, 
	csrf VARCHAR NOT NULL, 
	expires FLOAT NOT NULL, 
	PRIMARY KEY (hash)
)

;


CREATE TABLE states (
	device_id VARCHAR NOT NULL, 
	property VARCHAR NOT NULL, 
	value JSON NOT NULL, 
	unit VARCHAR NOT NULL, 
	observed FLOAT NOT NULL, 
	received FLOAT NOT NULL, 
	source VARCHAR NOT NULL, 
	PRIMARY KEY (device_id, property)
)

;

CREATE INDEX ix_commands_latest ON commands (device_id, created);

CREATE INDEX ix_commands_created ON commands (created);

CREATE INDEX ix_events_received ON events (received);

CREATE INDEX ix_events_status ON events (status);

CREATE INDEX ix_history ON measurements (device_id, property, observed, id);

CREATE INDEX ix_measurements_observed ON measurements (observed);