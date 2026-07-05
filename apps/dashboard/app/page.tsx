import Link from "next/link";
import fa from "@/locales/fa.json";

export default function Home() {
  return (
    <main>
      <h1>{fa.app.title}</h1>
      <p>{fa.app.tagline}</p>
      <p>
        <Link href="/login">{fa.app.go_login}</Link>
        {" · "}
        <Link href="/register">{fa.app.go_register}</Link>
      </p>
      <section>
        <h2>{fa.app.status_heading}</h2>
        <p>{fa.app.status_ok}</p>
        <p>{fa.app.milestone}</p>
      </section>
    </main>
  );
}
