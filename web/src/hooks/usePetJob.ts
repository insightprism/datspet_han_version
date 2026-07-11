"use client";

/**
 * usePetJob — submit a generation to the Pet Maker API and poll it to
 * completion. Shared by the Describe page and the Design page so the
 * job lifecycle (submit → poll → done/error) lives in exactly one place.
 */

import { useEffect, useRef, useState } from "react";
import { generatePet, getJob, type JobStatus } from "@/lib/api";

export function usePetJob() {
  const [job, setJob] = useState<JobStatus | null>(null);
  const [error, setError] = useState("");
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => () => {
    if (pollRef.current) clearInterval(pollRef.current);
  }, []);

  async function submit(fd: FormData) {
    setError("");
    try {
      const { job_id } = await generatePet(fd);
      setJob({
        id: job_id, name: "", status: "queued", progress: 0,
        message: "Queued…", breed_id: null, error: null,
      });
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = setInterval(async () => {
        try {
          const j = await getJob(job_id);
          setJob(j);
          if (j.status === "done" || j.status === "error") {
            if (pollRef.current) clearInterval(pollRef.current);
            pollRef.current = null;
          }
        } catch (e) {
          setError(e instanceof Error ? e.message : "Polling error");
        }
      }, 1500);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Server error");
    }
  }

  function reset() {
    setJob(null);
    setError("");
  }

  const busy = job !== null && (job.status === "queued" || job.status === "running");
  const done = job !== null && job.status === "done";
  return { job, error, setError, submit, reset, busy, done };
}
