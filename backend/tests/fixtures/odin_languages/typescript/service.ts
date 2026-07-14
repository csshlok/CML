import { run } from "./helpers";
export interface Runnable { execute(): void }
export class Service extends Base implements Runnable {
  execute() { run(); }
}
