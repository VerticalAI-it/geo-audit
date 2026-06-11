const { Pool } = require('pg');

const pool = new Pool({
  host:     process.env.DB_HOST,
  port:     parseInt(process.env.DB_PORT, 10) || 5432,
  database: process.env.DB_NAME     || 'postgres',
  user:     process.env.DB_USER     || 'postgres',
  password: process.env.DB_PASSWORD,
  ssl:      { rejectUnauthorized: false },
});

pool.on('error', (err) => {
  console.error('Unexpected DB error', err);
  process.exit(-1);
});

module.exports = pool;
