import { Atom, BriefcaseBusiness, Home, Server } from "lucide-react";

const links = [
  { label: "Home", href: "#main", icon: Home, current: true },
  { label: "Campaigns", href: "#existing-campaigns", icon: BriefcaseBusiness },
  { label: "Zeus jobs", icon: Server, later: true },
] as const;

export function AppHeader() {
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
          if ("later" in item) {
            return (
              <span className="nav-disabled" key={item.label} aria-disabled="true" title="Available in a later milestone">
                <Icon aria-hidden="true" />
                <span>{item.label}</span>
                <small>Later</small>
              </span>
            );
          }
          return (
            <a key={item.label} href={item.href} aria-current={"current" in item ? "page" : undefined}>
              <Icon aria-hidden="true" />
              <span>{item.label}</span>
            </a>
          );
        })}
      </nav>
    </header>
  );
}
