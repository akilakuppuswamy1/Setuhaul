export function ConcurrencyPage() {
  return (
    <div>
      <h1 className="page-title">Concurrent capacity</h1>
      <p className="lede">
        This screen explains Step 6 behavior. The frontend does not simulate locking or decide a winner.
      </p>
      <section className="card card-pad">
        <div className="kicker">Slot capacity 1</div>
        <pre style={{ fontFamily: "IBM Plex Sans, sans-serif", lineHeight: 1.8 }}>
{`DRIVER A ───────┐
                │
                ├── SLOT CAPACITY 1
                │
DRIVER B ───────┘`}
        </pre>
        <dl className="kv">
          <dt>Driver A</dt>
          <dd>CONFIRMED — first successful Step 6 allocation</dd>
          <dt>Driver B</dt>
          <dd>CONFLICT — HTTP 409, no silent retry</dd>
        </dl>
      </section>
      <section className="card card-pad" style={{ marginTop: 16 }}>
        <div className="kicker">Backend evidence</div>
        <p>
          Concurrent correctness is covered by <code>tests/test_step6_concurrency.py</code> and{" "}
          <code>tests/test_step7_concurrency.py</code>. Those tests call AllocationService / ProposalService against
          PostgreSQL with row locks. There is no classroom API that safely fires two live confirmations from this UI
          without mutating shared demo data, so this page does not invent one.
        </p>
        <p style={{ color: "var(--muted)", marginBottom: 0 }}>
          Allocation policy is first-successful-confirm (FCFS-style): SHOW and PROPOSE do not reserve the slot.
          Runtime confirmation still uses POST /proposals/{"{id}"}/accept, which revalidates (Step 5) and allocates
          (Step 6). Concurrent confirmation evidence is Request A → 200 and Request B → 409 from that backend path,
          not a frontend calculation.
        </p>
      </section>
    </div>
  );
}
