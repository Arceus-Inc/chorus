CREATE TABLE staffing_request_need (
    request_id                  TEXT NOT NULL REFERENCES staffing_request(id),
    profession                  TEXT NOT NULL,
    count                       INTEGER NOT NULL,
    PRIMARY KEY (request_id, profession)
);