import type { Project } from "./types";

const MAX_DEPTH = 50;

// Snapshot-based (not command-based) since Project is small, plain JSON -
// simpler and less error-prone than modeling every mutation as an
// invertible command, at the cost of a bit more memory per undo step
// (acceptable for a project with at most a few dozen small nodes).
export class History {
  private stack: string[] = [];
  private redoStack: string[] = [];

  constructor(private getState: () => Project, private setState: (p: Project) => void) {}

  // Call BEFORE a mutation happens, capturing the state to return to.
  push(): void {
    this.stack.push(JSON.stringify(this.getState()));
    if (this.stack.length > MAX_DEPTH) this.stack.shift();
    this.redoStack = [];
  }

  canUndo(): boolean {
    return this.stack.length > 0;
  }

  undo(): boolean {
    const prev = this.stack.pop();
    if (prev === undefined) return false;
    this.redoStack.push(JSON.stringify(this.getState()));
    this.setState(JSON.parse(prev));
    return true;
  }
}
