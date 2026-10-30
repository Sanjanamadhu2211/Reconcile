import Link from "next/link";
import { getCategoryLabel, getStatusLabel, type ExceptionItem } from "@/lib/exceptions";
import styles from "./exceptions.module.css";

interface ExceptionTableProps {
  exceptions: ExceptionItem[];
}

export default function ExceptionTable({ exceptions }: ExceptionTableProps) {
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <caption className={styles.visuallyHidden}>Exceptions for the latest run</caption>
        <thead>
          <tr>
            <th scope="col">Category</th>
            <th scope="col">Status</th>
            <th scope="col">Source</th>
            <th scope="col">External ID</th>
            <th scope="col" className={styles.numeric}>
              Amount
            </th>
          </tr>
        </thead>
        <tbody>
          {exceptions.map((exception) => {
            const { transaction, import_row: importRow } = exception;
            return (
              <tr key={exception.id}>
                <td>{getCategoryLabel(exception.category)}</td>
                <td>{getStatusLabel(exception.status)}</td>
                <td>{transaction?.source_name ?? "—"}</td>
                <td>
                  <Link href={`/exceptions/${exception.id}`} className={styles.link}>
                    {transaction?.external_id ?? `Row ${importRow?.row_number}`}
                  </Link>
                </td>
                <td className={styles.numeric}>
                  {transaction ? `${transaction.amount} ${transaction.currency}` : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
