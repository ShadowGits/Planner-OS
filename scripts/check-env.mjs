const requiredServer = [
  "SUPABASE_URL",
  "SUPABASE_ANON_KEY",
  "SUPABASE_SERVICE_ROLE_KEY",
  "GOOGLE_OAUTH_REDIRECT_URI",
];

const requiredPublic = [
  ["NEXT_PUBLIC_SUPABASE_URL", "SUPABASE_URL"],
  ["NEXT_PUBLIC_SUPABASE_ANON_KEY", "SUPABASE_ANON_KEY"],
];

const requiredAlternatives = [
  ["GOOGLE_WEB_CLIENT_ID", "GOOGLE_CLIENT_ID"],
  ["GOOGLE_WEB_CLIENT_SECRET", "GOOGLE_CLIENT_SECRET"],
];

const missing = requiredServer.filter((name) => !process.env[name]);
for (const [publicName, serverName] of requiredPublic) {
  if (!process.env[publicName] && !process.env[serverName]) missing.push(`${publicName} (or ${serverName})`);
}
for (const [preferredName, legacyName] of requiredAlternatives) {
  if (!process.env[preferredName] && !process.env[legacyName]) missing.push(`${preferredName} (or ${legacyName})`);
}

if (missing.length) {
  console.error(`Missing Planner OS environment variables: ${missing.join(", ")}`);
  process.exit(1);
}

const redirect = new URL(process.env.GOOGLE_OAUTH_REDIRECT_URI);
if (redirect.protocol !== "https:" && redirect.hostname !== "localhost" && redirect.hostname !== "127.0.0.1") {
  console.error("GOOGLE_OAUTH_REDIRECT_URI must use HTTPS outside local development");
  process.exit(1);
}

console.log("Planner OS environment is configured.");
