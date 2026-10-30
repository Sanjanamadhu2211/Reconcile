import type { Dispatch } from "react";
import { formatRangeText } from "@/lib/exceptions";
import styles from "./exceptions.module.css";

interface PaginationProps {
  page: number;
  rowCount: number;
  hasNext: boolean;
  onPageChange: Dispatch<number>;
}

export default function Pagination({ page, rowCount, hasNext, onPageChange }: PaginationProps) {
  return (
    <nav aria-label="Pagination" className={styles.pagination}>
      <p aria-live="polite">{formatRangeText(page, rowCount)}</p>
      <div>
        <button
          type="button"
          className={styles.button}
          onClick={() => onPageChange(page - 1)}
          disabled={page === 1}
        >
          Previous
        </button>
        <button
          type="button"
          className={styles.button}
          onClick={() => onPageChange(page + 1)}
          disabled={!hasNext}
        >
          Next
        </button>
      </div>
    </nav>
  );
}
