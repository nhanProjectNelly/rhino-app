-- Add role to users (admin | user). Run once.
-- ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(16) DEFAULT 'user';
-- Then set admin: UPDATE users SET role = 'admin' WHERE username = 'your_admin_username';

-- SQLite:
ALTER TABLE users ADD COLUMN role VARCHAR(16) DEFAULT 'user';

-- Add reported/corrected to prediction_records
ALTER TABLE prediction_records ADD COLUMN reported BOOLEAN DEFAULT 0;
ALTER TABLE prediction_records ADD COLUMN corrected_identity_id INTEGER REFERENCES rhino_identities(id);
