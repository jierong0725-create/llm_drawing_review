// app/static/jsx/marker_label.jsx
function MarkerLabel({ dim, zoom, offsetX, offsetY, isSelected, onClick }) {
  const colorMap = {
    pending: "var(--signal-gray)",
    confirmed: "var(--signal-green)",
    questionable: "var(--signal-amber)",
  };
  const x = dim.anchor_x * zoom + offsetX;
  const y = dim.anchor_y * zoom + offsetY;
  const size = Math.max(22, 26 / Math.sqrt(Math.max(zoom, 0.1)));

  return React.createElement("div", {
    style: {
      position: "absolute", left: x, top: y,
      width: size, height: size,
      transform: "translate(-50%, -50%)",
      backgroundColor: colorMap[dim.review_status] || colorMap.pending,
      color: "#fff", display: "flex", alignItems: "center", justifyContent: "center",
      fontFamily: "var(--font-mono)", fontSize: Math.max(11, 11 / Math.sqrt(Math.max(zoom, 0.1))),
      fontWeight: 700, borderRadius: "var(--radius)",
      border: isSelected ? "2px solid var(--accent-primary)" : "1px solid transparent",
      cursor: "pointer", zIndex: isSelected ? 20 : 10,
      boxShadow: isSelected ? "0 0 0 3px rgba(240,165,0,0.3)" : "none",
      transition: "box-shadow 0.15s, border-color 0.15s",
    },
    onClick: (e) => { e.stopPropagation(); onClick(dim.id); },
    title: dim.value,
  }, dim.sequence);
}

Object.assign(window, { MarkerLabel });
