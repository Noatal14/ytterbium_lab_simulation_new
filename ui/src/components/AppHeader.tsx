import { Atom, Home, Server } from "lucide-react";

export function AppHeader({ page, onNavigate }: { page: "home" | "jobs"; onNavigate: (page: "home" | "jobs") => void }) {
  const links = [
    { label: "Home", page: "home" as const, href: "#main", icon: Home },
    { label: "Zeus connection", page: "jobs" as const, href: "#jobs", icon: Server },
  ];
  return (
    <header className="app-header">
      <div className="brand">
        <span className="brand-mark" aria-hidden="true"><Atom /></span>
        <span>
          <strong>Simulation control center</strong>
          <small>Yb-171 laser-cooling campaigns</small>
        </span>
      </div>
      <nav aria-label="Primary navigation">
        {links.map((item) => {
          const Icon = item.icon;
          return (
            <a key={item.label} href={item.href} aria-current={(item.page === "jobs" ? page === "jobs" : page === "home") ? "page" : undefined} onClick={(event) => { event.preventDefault(); onNavigate(item.page); }}>
              <Icon aria-hidden="true" />
              <span>{item.label}</span>
            </a>
          );
        })}
      </nav>
    </header>
  );
}
