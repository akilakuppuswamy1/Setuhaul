import { useNavigate } from "react-router-dom";
import { DEMO_SCENARIOS } from "@/demo/scenarios";
import { useOps } from "@/state/OpsProvider";

export function DemoScenariosPage() {
  const navigate = useNavigate();
  const { setComposer, send } = useOps();

  return (
    <div>
      <h1 className="page-title">Demo scenarios</h1>
      <p className="lede">
        Suggested driver messages only. Results always come from the live backend. Nothing here fakes feasibility,
        allocation, or confirmation.
      </p>
      <div className="scenario-list">
        {DEMO_SCENARIOS.map((scenario) => (
          <button
            key={scenario.id}
            type="button"
            className="scenario-card"
            onClick={() => {
              if ("route" in scenario && scenario.route) {
                navigate(scenario.route);
                return;
              }
              setComposer(scenario.message);
              navigate("/");
            }}
          >
            <div className="kicker">{scenario.id}</div>
            <strong>{scenario.title}</strong>
            <p style={{ color: "var(--muted)", marginBottom: 0 }}>{scenario.hint}</p>
          </button>
        ))}
      </div>
      <p style={{ marginTop: 24 }}>
        <button
          type="button"
          className="btn"
          onClick={() => {
            setComposer(DEMO_SCENARIOS[0].message);
            navigate("/");
            void send(DEMO_SCENARIOS[0].message);
          }}
        >
          Start hero delay message
        </button>
      </p>
    </div>
  );
}
