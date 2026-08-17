// Seeds a tiny demo collection and provisions a GENUINELY restricted
// read-only user via MongoDB's built-in "read" role. Verified against in
// tests/integration/test_readonly_connectors.py. Runs as the root user
// (MONGO_INITDB_ROOT_USERNAME/PASSWORD, per the mongo image's
// docker-entrypoint convention), which is required to enable auth at all —
// without a root user, MongoDB runs with no authentication and every
// connection has full read/write access regardless of role.

db = db.getSiblingDB("source_demo");

db.customers.insertMany([
  { first_name: "  John  ", last_name: "Smith", email: "john.smith@example.com" },
  { first_name: "José", last_name: "García", email: "jose.garcia@example.com" },
  { first_name: "JOHN", last_name: "SMITH", email: null },
]);

db.createUser({
  user: "readonly_user",
  pwd: "readonly_pass",
  roles: [{ role: "read", db: "source_demo" }],
  // Explicitly no readWrite/dbAdmin/root role — "read" grants find() only.
});
