import historical from "../../../tests/contracts/v1/workflow_api_success.json";
import { zeusProjectDirectory } from "../api/zeusEnvironment";

// Keep the backend's historical snapshot unchanged. Only the closed deployment
// root changes for current-default UI fixtures; physics, counts and hashes do not.
const snapshot: typeof historical = JSON.parse(JSON.stringify(historical).replaceAll(
  "/home/tal.noa/ytterbium_lab_simulation_new", zeusProjectDirectory("tal.noa"),
));
export default snapshot;
