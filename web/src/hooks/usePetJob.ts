"use client";

/**
 * usePetJob — submit a generation to the Pet Maker API and poll it to
 * completion. Shared by the Describe page and the Design page so the
 * job lifecycle (submit → poll → done/error/canceled) lives in exactly one place.
 *
 * THE RUNNING JOB LIVES IN THE URL (`?job=<id>`), not in React state alone.
 *
 * A build takes ~3 minutes, and a full-page navigation in the middle of one used to
 * lose it completely: the pet finished on the server, landed as a draft nobody could
 * see, and was deleted by the next build's draft purge. The DatsMe sign-in bounce is
 * exactly such a navigation, so "design a pet, then sign in to adopt it" — the front
 * door's whole invitation — destroyed the thing it invited.
 * (Measured on staging 2026-07-30: pet 332793aaaa66 "Bat", 828 KB of finished bundle,
 * correctly re-owned by the sweep and reachable from nowhere.)
 *
 * The id is the only thing needed to get back: GET /api/job/{id} is deliberately
 * unscoped, so it survives the identity CHANGING underneath it, which is precisely
 * what a mid-build sign-in does. Putting it in the URL — via replaceState, so no
 * remount and no history entry — means a reload, a bfcache restore, and a sign-in
 * round trip all recover the same way, without browser-persisted user state
 * (SPEC_DATSPET_FEDERATED_SESSION §5.4 forbids that, and rightly).
 */

import { useEffect, useRef, useState } from "react";
import { generatePet, getJob, stopJob, type JobStatus } from "@/lib/api";

const TERMINAL = new Set(["done", "error", "canceled"]);

/** The query parameter that carries an in-flight (or just-finished) build. */
export const JOB_URL_PARAM = "job";

/** Put the job in the URL, or take it out. replaceState: no navigation, no remount,
 *  and no history entry the Back button would have to step through. */
function setJobInUrl(jobId: string | null): void {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  if (jobId) url.searchParams.set(JOB_URL_PARAM, jobId);
  else url.searchParams.delete(JOB_URL_PARAM);
  window.history.replaceState(null, "", url.toString());
}

function jobFromUrl(): string | null {
  if (typeof window === "undefined") return null;
  return new URLSearchParams(window.location.search).get(JOB_URL_PARAM);
}

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

  // Reattach to a build already in flight — the mid-build sign-in case (see the
  // module docstring). Fetches ONCE immediately rather than waiting out a poll
  // interval, so the page paints the real state instead of a blank step 3.
  useEffect(() => {
    const jobId = jobFromUrl();
    if (!jobId) return;
    let cancelled = false;
    getJob(jobId)
      .then((j) => {
        if (cancelled) return;
        setJob(j);
        if (TERMINAL.has(j.status)) return;   // finished while we were away
        jobIdRef.current = jobId;
        startPoll(jobId);
      })
      .catch(() => {
        // Unknown or long-gone id (JOBS is in-memory, so a backend restart clears
        // it). Drop it quietly and show the designer's normal empty state — an
        // error banner about a job the user did not ask to resume is noise.
        if (!cancelled) setJobInUrl(null);
      });
    return () => { cancelled = true; };
    // Mount only: the URL is read once, and every later change goes through
    // submit/reset, which own the param themselves.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
      // Before anything else can navigate away — the id is now recoverable.
      setJobInUrl(job_id);
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
    // "Design another" — this build is deliberately finished with, so stop
    // resurrecting it on every reload.
    setJobInUrl(null);
  }

  const busy = job !== null && (job.status === "queued" || job.status === "running");
  const done = job !== null && job.status === "done";
  return { job, error, setError, submit, reset, stop, busy, done };
}
