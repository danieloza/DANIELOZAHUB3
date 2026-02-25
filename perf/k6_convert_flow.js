import http from "k6/http";
import { check, sleep } from "k6";

export const options = {
  vus: 10,
  duration: "45s",
  thresholds: {
    http_req_failed: ["rate<0.03"],
    http_req_duration: ["p(95)<1200"],
  },
};

const baseUrl = __ENV.BASE_URL || "http://127.0.0.1:8000";
const tenant = __ENV.TENANT || "danex";

function reservationPayload() {
  const dt = new Date();
  dt.setDate(dt.getDate() + 2);
  dt.setHours(13, 0, 0, 0);
  return {
    requested_dt: dt.toISOString().slice(0, 19),
    client_name: `Convert Client ${__VU}-${__ITER}`,
    service_name: "Modelowanie",
    phone: `+48789${String(__ITER % 100000).padStart(5, "0")}`,
  };
}

export default function () {
  const headers = { "Content-Type": "application/json", "X-Tenant-Slug": tenant, "X-Actor-Email": "perf@salonos.local", "X-Actor-Role": "manager" };

  const createRes = http.post(
    `${baseUrl}/public/${tenant}/reservations`,
    JSON.stringify(reservationPayload()),
    { headers: { "Content-Type": "application/json" } }
  );
  if (createRes.status !== 200) {
    check(createRes, { "reservation created": (r) => r.status === 200 });
    sleep(0.5);
    return;
  }

  const reservation = createRes.json();
  const convertRes = http.post(
    `${baseUrl}/api/reservations/${reservation.id}/convert`,
    JSON.stringify({ employee_name: "Magda", price: 200 }),
    { headers }
  );
  check(convertRes, {
    "convert success": (r) => r.status === 200 || r.status === 400,
  });
  sleep(0.5);
}
