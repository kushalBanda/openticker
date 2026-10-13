import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { type AgentStep, keys } from "../api/queries";
import { useStream } from "./prices";

// A chat's steps as the agent works (ADR 40): the stream sends a running
// turn's steps from an index on, replacing what the page had from there, and
// says when a turn is asked, starts or ends, when the chat is read again.

/** The live steps of the watched chat's turns, by job id. */
export function useThreadWatch(threadId: string | null): Map<string, AgentStep[]> {
  const { stream } = useStream();
  const client = useQueryClient();
  const [steps, setSteps] = useState<Map<string, AgentStep[]>>(() => new Map());

  useEffect(() => {
    setSteps(new Map());
    if (threadId === null) return;
    const off = stream.onThread((news) => {
      if (news.thread_id !== threadId) return;
      if (news.type === "thread_steps") {
        setSteps((had) => {
          const next = new Map(had);
          const kept = (had.get(news.job_id) ?? []).slice(0, news.from_index);
          next.set(news.job_id, [...kept, ...news.steps]);
          return next;
        });
      } else {
        client.invalidateQueries({ queryKey: keys.agentThreads });
      }
    });
    const unwatch = stream.watchThread(threadId);
    return () => {
      off();
      unwatch();
    };
  }, [stream, client, threadId]);

  return steps;
}
