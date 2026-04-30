// app/static/jsx/stamp.jsx
function Stamp({ type, date }) {
  // type: "approved" | "rejected"
  const isApproved = type === "approved";
  return React.createElement("div", {
    style: {
      ...stampStyles.base, transform: `rotate(${isApproved ? -12 : 12}deg)`,
      color: isApproved ? "var(--signal-green)" : "var(--signal-red)",
      borderColor: isApproved ? "var(--signal-green)" : "var(--signal-red)",
    }
  },
    React.createElement("div", { style: stampStyles.icon }, isApproved ? "✓" : "✕"),
    React.createElement("div", { style: stampStyles.label }, isApproved ? "APPROVED" : "REJECTED"),
    React.createElement("div", { style: stampStyles.date }, date)
  );
}

const stampStyles = {
  base: {
    display: "inline-flex", flexDirection: "column", alignItems: "center", gap: 2,
    border: "2px solid", borderRadius: 4, padding: "8px 20px",
    fontFamily: "var(--font-display)", letterSpacing: "0.1em",
    opacity: 0.85, userSelect: "none", pointerEvents: "none",
  },
  icon: { fontSize: 24, fontWeight: 700 },
  label: { fontSize: 10, fontWeight: 700 },
  date: { fontSize: 9, color: "var(--ink-secondary)", letterSpacing: "0.05em" },
};

Object.assign(window, { Stamp, stampStyles });
