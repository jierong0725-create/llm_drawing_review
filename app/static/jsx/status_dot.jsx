// app/static/jsx/status_dot.jsx
// status: "approved" | "rejected" | "pending" | "questionable" | "processing"
function StatusDot({ status, label, pulse = false }) {
  const colorMap = {
    approved: "var(--signal-green)",
    rejected: "var(--signal-red)",
    pending: "var(--signal-gray)",
    questionable: "var(--signal-amber)",
    processing: "var(--accent-primary)",
  };
  return React.createElement("span", { style: statusDotStyles.wrapper },
    React.createElement("span", {
      style: {
        ...statusDotStyles.dot,
        backgroundColor: colorMap[status] || colorMap.pending,
        animation: pulse && status === "processing" ? "pulse 1.5s ease-in-out infinite" : "none",
      }
    }),
    label && React.createElement("span", { style: statusDotStyles.label }, label)
  );
}

const statusDotStyles = {
  wrapper: { display: "inline-flex", alignItems: "center", gap: 6 },
  dot: { width: 8, height: 8, borderRadius: "var(--radius)" },
  label: { fontSize: 12, color: "var(--ink-secondary)" },
};

Object.assign(window, { StatusDot, statusDotStyles });
