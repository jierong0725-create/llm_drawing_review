// app/static/jsx/data_table.jsx
// columns: [{ key, label, render? }]
// data: array of objects
// onRowClick: (row) => void
function DataTable({ columns, data, onRowClick, emptyText = "暂无数据" }) {
  return React.createElement("table", { className: "industrial" },
    React.createElement("thead", null,
      React.createElement("tr", null,
        columns.map(col => React.createElement("th", { key: col.key }, col.label))
      )
    ),
    React.createElement("tbody", null,
      data.length === 0
        ? React.createElement("tr", null,
            React.createElement("td", { colSpan: columns.length, style: { textAlign: "center", color: "var(--ink-disabled)", padding: 40 } }, emptyText))
        : data.map((row, i) =>
            React.createElement("tr", {
              key: row.id || i,
              onClick: () => onRowClick && onRowClick(row),
              style: onRowClick ? { cursor: "pointer" } : {},
            },
              columns.map(col =>
                React.createElement("td", { key: col.key },
                  col.render ? col.render(row[col.key], row) : row[col.key]
                )
              )
            )
          )
    )
  );
}

Object.assign(window, { DataTable });
