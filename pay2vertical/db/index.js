const { Pool } = require('pg');

// pg-connection-string chokes on Supabase's "postgres.projectref" username.
// Parse with Node's URL instead and pass individual params.
const dbUrl = new URL(process.env.DATABASE_URL);

const pool = new Pool({
  host:     dbUrl.hostname,
  port:     parseInt(dbUrl.port, 10) || 5432,
  database: dbUrl.pathname.replace(/^\//, ''),
  user:     decodeURIComponent(dbUrl.username),
  password: decodeURIComponent(dbUrl.password),
  ssl:      { rejectUnauthorized: false },
});

pool.on('error', (err) => {
  console.error('Unexpected DB error', err);
  process.exit(-1);
});

module.exports = pool;
