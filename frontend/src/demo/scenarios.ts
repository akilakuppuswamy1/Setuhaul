export const DEMO_SCENARIOS = [
  {
    id: "01",
    title: "Delay & ETA update",
    hint: "Records a driver ETA through Step 4. Does not book.",
    message:
      "I'm going to be 2 hours late. I was supposed to reach by 6:30 PM, but I'll reach around 8:30 PM because of traffic.",
  },
  {
    id: "02",
    title: "Find alternative options",
    hint: "Asks Step 5 for feasible slots. Showing is not proposing.",
    message: "My ETA is 8:30 PM. What options do I have?",
  },
  {
    id: "03",
    title: "Select second option",
    hint: "Creates a Step 7 proposal. Not a confirmation.",
    message: "The second one works, but I need to leave by 9:30 PM.",
  },
  {
    id: "04",
    title: "Check confirmation status",
    hint: "Read-only. Must not call accept.",
    message: "Has it been confirmed?",
  },
  {
    id: "05",
    title: "Confirm appointment",
    hint: "Explicit confirm → Step 7 accept → Step 5 → Step 6.",
    message: "Confirm it.",
  },
  {
    id: "06",
    title: "Stale proposal",
    hint: "Use after capacity has already been taken. Expect 409 / stale.",
    message: "Confirm it.",
  },
  {
    id: "07",
    title: "Human escalation",
    hint: "Records review. Does not claim a human has acted.",
    message: "I need to talk to a human operator.",
  },
  {
    id: "08",
    title: "Facility schedule",
    hint: "Opens the read-only Step 9 page.",
    message: "",
    route: "/facility-schedule",
  },
  {
    id: "09",
    title: "Concurrent capacity conflict",
    hint: "Explains Step 6 locking using backend test evidence.",
    message: "",
    route: "/concurrency",
  },
  {
    id: "leave-by",
    title: "Leave-by constraint",
    hint: "Stores a leave-by time before options are requested.",
    message: "I also have an emergency and I need to leave by 9:30 PM.",
  },
] as const;
