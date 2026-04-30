// app/static/jsx/app_shell.jsx
function AppShell({ breadcrumbs, children }) {
  return React.createElement("div", null,
    React.createElement("nav", { style: appShellStyles.nav },
      React.createElement("a", { href: "/parts/", style: appShellStyles.brand }, "⚙ 工程图纸审核"),
      breadcrumbs && breadcrumbs.map((crumb, i) =>
        React.createElement("span", { key: i },
          React.createElement("span", { style: appShellStyles.separator }, " / "),
          crumb.href
            ? React.createElement("a", { href: crumb.href, style: appShellStyles.link }, crumb.label)
            : React.createElement("span", { style: appShellStyles.current }, crumb.label)
        )
      )
    ),
    React.createElement("main", { style: appShellStyles.main }, children)
  );
}

const appShellStyles = {
  nav: { display: "flex", alignItems: "center", gap: "var(--space-8)",
         height: 32, padding: "0 var(--space-16)", background: "var(--bg-surface)",
         borderBottom: "1px solid var(--border-color)", fontSize: 13 },
  brand: { color: "var(--accent-primary)", textDecoration: "none", fontWeight: 600,
           fontFamily: "var(--font-display)", letterSpacing: "0.04em" },
  link: { color: "var(--ink-secondary)", textDecoration: "none" },
  current: { color: "var(--ink)" },
  separator: { color: "var(--ink-disabled)" },
  main: { height: "calc(100vh - 32px)", display: "flex", flexDirection: "column" },
};

Object.assign(window, { AppShell, appShellStyles });
