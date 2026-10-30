const EXPORTS = [
  { file: "matches.csv", label: "Download matches" },
  { file: "exceptions.csv", label: "Download exceptions" },
  { file: "import-errors.csv", label: "Download import errors" },
];

interface ExportLinksProps {
  workspaceId: string;
}

export default function ExportLinks({ workspaceId }: ExportLinksProps) {
  return (
    <div className="page-actions">
      {EXPORTS.map(({ file, label }) => (
        <a
          key={file}
          href={`/api/v1/workspaces/${workspaceId}/exports/${file}`}
          download
          className="action-link"
        >
          {label}
        </a>
      ))}
    </div>
  );
}
