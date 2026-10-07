BEGIN;

CREATE TABLE IF NOT EXISTS public.states (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS public.high_courts (
    id SERIAL PRIMARY KEY,
    state_id INTEGER NOT NULL REFERENCES public.states(id),
    name TEXT NOT NULL,
    UNIQUE (state_id, name)
);

COMMIT;
