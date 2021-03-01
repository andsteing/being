"use strict";
import {Deque} from "/static/js/deque.js";
import {last_element} from "/static/js/utils.js";



/**
 * Edit history container.
 */
export class History {
    constructor(maxlen=20) {
        this.past = new Deque([], maxlen);
        this.future = new Deque([], maxlen);
    }


    /**
     * History length. Past and future.
     */
    get length() {
        return this.past.length + this.future.length;
    }


    /**
     * History can be undone.
     */
    get undoable() {
        return this.past.length > 1;
    }


    /**
     * History can be restored.
     */
    get redoable() {
        return this.future.length > 0;
    }


    /**
     * Capture a new state and add it to the history. Will clear off head.
     */
    capture(state) {
        this.future.clear();
        this.past.push(state);
    }


    /**
     * Retrieve current state.
     */
    retrieve() {
        return last_element(this.past);
    }


    /**
     * Wind back one state.
     */
    undo() {
        if (!this.undoable)
            throw "Nothing to undo!";

        const current = this.past.pop();
        this.future.appendleft(current);
        return this.retrieve();
    }


    /**
     * Rewind one state.
     */
    redo() {
        if (!this.redoable)
            throw "Nothing to redo!";

        const previous = this.future.popleft();
        this.past.push(previous);
        return this.retrieve();
    }


    /**
     * Clear complete history.
     */
    clear() {
        this.past.clear();
        this.future.clear();
    }
}