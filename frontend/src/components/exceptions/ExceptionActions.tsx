import styles from "./exceptions.module.css";

// Placeholder: the propose, approve, reject and reopen workflow replaces this panel.
export default function ExceptionActions() {
  return (
    <section className={styles.panel} aria-labelledby="exception-actions-heading">
      <h2 id="exception-actions-heading">Actions</h2>
      <p className={styles.muted}>Resolution actions will appear here.</p>
    </section>
  );
}
