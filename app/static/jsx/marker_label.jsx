// app/static/jsx/marker_label.jsx
function MarkerLabel({ dim, zoom, offsetX, offsetY, isSelected, onClick, onContextMenu }) {
  const colorMap = {
    pending: "var(--signal-gray)",
    confirmed: "var(--signal-green)",
    questionable: "var(--signal-amber)",
    rejected: "var(--signal-red)",
  };
  const x = dim.anchor_x * zoom + offsetX;
  const y = dim.anchor_y * zoom + offsetY;
  const size = Math.max(22, 26 / Math.sqrt(Math.max(zoom, 0.1)));
  const fontSize = Math.max(11, 11 / Math.sqrt(Math.max(zoom, 0.1)));

  return (
    <div
      data-marker="true"
      style={{
        position: "absolute", left: x, top: y,
        width: size, height: size,
        transform: "translate(-50%, -50%)",
        backgroundColor: colorMap[dim.review_status] || colorMap.pending,
        color: "#fff", display: "flex", alignItems: "center", justifyContent: "center",
        fontFamily: "var(--font-mono)", fontSize,
        fontWeight: 700, borderRadius: "var(--radius)",
        border: isSelected ? "2px solid var(--accent-primary)" : "1px solid rgba(0,0,0,0.15)",
        cursor: "pointer", zIndex: isSelected ? 20 : 10,
        boxShadow: isSelected ? "0 0 0 3px rgba(201,127,0,0.25)" : "0 1px 3px rgba(0,0,0,0.15)",
        transition: "box-shadow 0.15s, border-color 0.15s",
        userSelect: "none",
      }}
      onClick={(e) => { e.stopPropagation(); onClick(dim.id); }}
      onContextMenu={(e) => { e.preventDefault(); e.stopPropagation(); onContextMenu && onContextMenu(e, dim); }}
      title={dim.value}
    >
      {dim.sequence}
    </div>
  );
}

Object.assign(window, { MarkerLabel });
