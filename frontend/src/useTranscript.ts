import { useEffect, useReducer } from "react";
import { api } from "./types";
import type { Segment, Session, Update } from "./types";

type Connection = "connecting" | "connected" | "reconnecting" | "disconnected";
interface State {
  session: Session | null;
  segments: Record<string, Segment>;
  version: number;
  connection: Connection;
  error: string;
}
type Action =
  | { type: "connection"; connection: Connection }
  | { type: "update"; update: Update };
const initial: State = {
  session: null,
  segments: {},
  version: -1,
  connection: "connecting",
  error: "",
};

function reducer(state: State, action: Action): State {
  if (action.type === "connection")
    return { ...state, connection: action.connection };
  const update = action.update;
  if (update.type === "error" || update.type === "demo_error")
    return { ...state, error: update.message };
  if (update.version < state.version) return state;
  if (update.type === "snapshot") {
    return {
      ...state,
      session: update.session,
      version: update.version,
      segments: Object.fromEntries(
        update.segments.map((segment) => [segment.segment_id, segment]),
      ),
      error: "",
    };
  }
  if (update.version <= state.version) return state;
  if (update.type === "status")
    return { ...state, session: update.session, version: update.version };
  const segment = update.segment;
  const previous = state.segments[segment.segment_id];
  if (
    previous &&
    (previous.revision >= segment.revision ||
      (previous.is_final && !segment.is_final))
  ) {
    return { ...state, version: update.version };
  }
  return {
    ...state,
    version: update.version,
    segments: { ...state.segments, [segment.segment_id]: segment },
  };
}

export function useTranscript(
  id: string,
  onSession: (session: Session) => void,
) {
  const [state, dispatch] = useReducer(reducer, initial);
  useEffect(() => {
    let active = true;
    let socket: WebSocket | undefined;
    let timer: ReturnType<typeof setTimeout>;
    let attempt = 0;
    const controller = new AbortController();
    // The HTTP snapshot keeps saved history readable if WebSockets are unavailable.
    api<Update>(`/sessions/${id}`, { signal: controller.signal })
      .then((update) => {
        if (active) dispatch({ type: "update", update });
      })
      .catch((error) => {
        if (active)
          dispatch({
            type: "update",
            update: { type: "error", message: error.message },
          });
      });
    function connect() {
      if (!active) return;
      dispatch({
        type: "connection",
        connection: attempt ? "reconnecting" : "connecting",
      });
      socket = new WebSocket(
        `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/api/sessions/${id}/events`,
      );
      socket.onmessage = (event) => {
        if (!active) return;
        try {
          const update: Update = JSON.parse(event.data);
          dispatch({ type: "update", update });
          if (update.type === "snapshot") {
            attempt = 0;
            dispatch({ type: "connection", connection: "connected" });
          }
        } catch {
          socket?.close();
        }
      };
      socket.onclose = (event) => {
        if (!active) return;
        dispatch({ type: "connection", connection: "disconnected" });
        if (event.code === 1008) return;
        const delay = Math.min(1000 * 2 ** Math.min(attempt++, 5), 15000);
        timer = setTimeout(connect, delay);
      };
      socket.onerror = () => socket?.close();
    }
    connect();
    return () => {
      active = false;
      controller.abort();
      clearTimeout(timer);
      socket?.close();
    };
  }, [id]);
  useEffect(() => {
    if (state.session) onSession(state.session);
  }, [state.session, onSession]);
  return {
    ...state,
    segments: Object.values(state.segments).sort(
      (a, b) =>
        a.start_ms - b.start_ms || a.segment_id.localeCompare(b.segment_id),
    ),
  };
}
