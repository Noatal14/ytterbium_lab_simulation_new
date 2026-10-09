import { useCallback, useEffect, useRef, useState } from "react";
import type { Campaign, CampaignApi } from "../api/campaigns";

export function useCampaignQuery(api: CampaignApi) {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [invalidCount, setInvalidCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const request = useRef(0);

  const refresh = useCallback(async () => {
    const id = ++request.current;
    setLoading(true);
    setError(null);
    try {
      const result = await api.list();
      if (id !== request.current) return;
      setCampaigns(result.campaigns);
      setInvalidCount(result.invalid_count);
    } catch {
      if (id !== request.current) return;
      setError("Campaign records are unavailable. Start the local read-only service and try again.");
    } finally {
      if (id === request.current) setLoading(false);
    }
  }, [api]);

  useEffect(() => {
    void refresh();
    return () => { request.current += 1; };
  }, [refresh]);

  return { campaigns, invalidCount, loading, error, refresh };
}
