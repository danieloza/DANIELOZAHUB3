import http from "k6/http";
import { check, sleep } from "k6";

export const options = {
  vus: 20,
  duration: "60s",
  thresholds: {
    http_req_failed: ["rate<0.02"],
    http_req_duration: ["p(95)<800"],
  },
};

const baseUrl = __ENV.BASE_URL || "http://127.0.0.1:8000";
const tenant = __ENV.TENANT || "danex";

export default function () {
  const now = new Date();
  now.setHours(now.getHours() + 4);
  const payload = {
    requested_dt: now.toISOString().slice(0, 19),
    client_name: `Load Client ${__VU}-${__ITER}`,
    service_name: "Koloryzacja",
    phone: `+48123${String(__ITER % 100000).padStart(5, "0")}`,
  };

  const response = http.post(
    `${baseUrl}/public/${tenant}/reservations`,
    JSON.stringify(payload),
    { headers: { "Content-Type": "application/json" } }
  );
  check(response, {
    "reservation accepted": (r) => r.status === 200 || r.status === 429,
  });
  sleep(0.2);
}
