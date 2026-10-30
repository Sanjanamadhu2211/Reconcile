"use client";

import { useEffect, useMemo, useState, type Dispatch } from "react";
import {
  CATEGORY_LABELS,
  EXCEPTION_CATEGORIES,
  EXCEPTION_STATUSES,
  SOURCE_NAMES,
  STATUS_LABELS,
  debounce,
  type ExceptionFilters,
} from "@/lib/exceptions";
import styles from "./exceptions.module.css";

interface ExceptionFilterBarProps {
  filters: ExceptionFilters;
  onFilterChange: Dispatch<Partial<ExceptionFilters>>;
  onSearchChange: Dispatch<string>;
}

export default function ExceptionFilterBar({
  filters,
  onFilterChange,
  onSearchChange,
}: ExceptionFilterBarProps) {
  const [searchText, setSearchText] = useState(filters.search);
  const debouncedSearch = useMemo(() => debounce(onSearchChange, 300), [onSearchChange]);

  useEffect(() => () => debouncedSearch.cancel(), [debouncedSearch]);

  return (
    <div role="search" className={styles.filters}>
      <div className={styles.field}>
        <label htmlFor="exception-search">Search</label>
        <input
          id="exception-search"
          type="search"
          placeholder="External ID"
          value={searchText}
          onChange={(event) => {
            setSearchText(event.target.value);
            debouncedSearch(event.target.value);
          }}
        />
      </div>
      <div className={styles.field}>
        <label htmlFor="exception-category">Category</label>
        <select
          id="exception-category"
          value={filters.category}
          onChange={(event) =>
            onFilterChange({
              category: event.target.value as ExceptionFilters["category"],
              page: 1,
            })
          }
        >
          <option value="">All categories</option>
          {EXCEPTION_CATEGORIES.map((category) => (
            <option key={category} value={category}>
              {CATEGORY_LABELS[category]}
            </option>
          ))}
        </select>
      </div>
      <div className={styles.field}>
        <label htmlFor="exception-status">Status</label>
        <select
          id="exception-status"
          value={filters.status}
          onChange={(event) =>
            onFilterChange({ status: event.target.value as ExceptionFilters["status"], page: 1 })
          }
        >
          <option value="">All statuses</option>
          {EXCEPTION_STATUSES.map((status) => (
            <option key={status} value={status}>
              {STATUS_LABELS[status]}
            </option>
          ))}
        </select>
      </div>
      <div className={styles.field}>
        <label htmlFor="exception-source">Source</label>
        <select
          id="exception-source"
          value={filters.source}
          onChange={(event) =>
            onFilterChange({ source: event.target.value as ExceptionFilters["source"], page: 1 })
          }
        >
          <option value="">All sources</option>
          {SOURCE_NAMES.map((source) => (
            <option key={source} value={source}>
              {source}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}
