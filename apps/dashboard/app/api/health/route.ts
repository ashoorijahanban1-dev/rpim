// Same wire contract as rpim_shared.HealthStatus.
export function GET() {
  return Response.json({ status: "ok", service: "dashboard", leg: "iran" });
}
