"use client";

/**
 * usePetJob — submit a generation to the Pet Maker API and poll it to
 * completion. Shared by the Describe page and the Design page so the
 * job lifecycle (submit → poll → done/error/canceled) lives in exactly one place.
 */

import { useEffect, useRef, useState } from "react";
import { generatePet, getJob, stopJob, type JobStatus } from "@/lib/api";

const TERMINAL = new Set(["done", "error", "canceled"]);

export function usePetJob() {
  const [job, setJob] = useState<JobStatus | null>(null);
  const [error, setError] = useState("");
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const jobIdRef = useRef<string | null>(null);

  function clearPoll() {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }

  function startPoll(jobId: string) {
    clearPoll();
    pollRef.current = setInterval(async () => {
      try {
        const j = await getJob(jobId);
        setJob(j);
        if (TERMINAL.has(j.status)) {
          clearPoll();
          jobIdRef.current = null;
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : "Polling error");
      }
    }, 1500);
  }

  // Unmount cleanup.
  useEffect(() => () => clearPoll(), []);

  // §C / decision D-2: the GET /api/job poll IS the device-liveness beat the pool watches. Pause
  // it while the tab is hidden, so a backgrounded/closed app stops renewing the pool lease and the
  // build is abandonment-cancelled; resume when the user returns — unless the job already went
  // terminal (or the lease lapsed, in which case the resumed poll reports 'canceled').
  useEffect(() => {
    function onVisibility() {
      if (document.hidden) clearPoll();
      else if (jobIdRef.current) startPoll(jobIdRef.current);
    }
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
    // startPoll/clearPoll close over refs + stable setters only, so the first-render copies are safe.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function submit(fd: FormData) {
    setError("");
    try {
      const { job_id } = await generatePet(fd);
      jobIdRef.current = job_id;
      setJob({
        id: job_id, name: "", status: "queued", progress: 0,
        message: "Queued…", breed_id: null, error: null,
      });
      startPoll(job_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Server error");
    }
  }

  // User-initiated Stop (§11). Optimistically reflect 'canceled'; the server kills the pool job
  // and the next poll (if any) confirms the terminal state.
  async function stop() {
    const jobId = jobIdRef.current;
    if (!jobId) return;
    try {
      await stopJob(jobId);
    } catch {
      // best-effort — a poll will surface the real terminal state regardless
    }
    setJob((j) => (j ? { ...j, status: "canceled", message: "Stopped." } : j));
  }

  function reset() {
    clearPoll();
    jobIdRef.current = null;
    setJob(null);
    setError("");
  }

  const busy = job !== null && (job.status === "queued" || job.status === "running");
  const done = job !== null && job.status === "done";
  return { job, error, setError, submit, reset, stop, busy, done };
}
