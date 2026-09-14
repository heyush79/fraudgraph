package com.fraudgraph.cases.web;

import com.fraudgraph.cases.model.CaseStatus;
import com.fraudgraph.cases.model.FraudCase;
import com.fraudgraph.cases.service.CaseService;
import com.fraudgraph.cases.store.CaseRepository;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import java.util.List;
import java.util.Map;
import java.util.UUID;

@RestController
public class CaseController {
    private static final int MAX_LIMIT = 200;

    private final CaseService cases;

    public CaseController(CaseService cases) {
        this.cases = cases;
    }

    public record CasePage(List<FraudCase> items, long total, int limit, int offset) {}

    public record StatusChange(CaseStatus status) {}

    @GetMapping("/cases")
    public CasePage list(@RequestParam(required = false) String status,
                         @RequestParam(defaultValue = "50") int limit,
                         @RequestParam(defaultValue = "0") int offset) {
        CaseStatus parsed = parseStatus(status);
        int bounded = Math.max(1, Math.min(MAX_LIMIT, limit));
        CaseRepository.Page page = cases.list(parsed, bounded, Math.max(0, offset));
        return new CasePage(page.items(), page.total(), page.limit(), page.offset());
    }

    @GetMapping("/cases/{caseId}")
    public FraudCase get(@PathVariable UUID caseId) {
        return cases.get(caseId).orElseThrow(() -> notFound(caseId));
    }

    @PatchMapping("/cases/{caseId}/status")
    public FraudCase changeStatus(@PathVariable UUID caseId, @RequestBody StatusChange body) {
        if (body == null || body.status() == null) {
            throw new ResponseStatusException(org.springframework.http.HttpStatus.BAD_REQUEST,
                    "status is required, one of " + List.of(CaseStatus.values()));
        }
        try {
            return cases.changeStatus(caseId, body.status()).orElseThrow(() -> notFound(caseId));
        } catch (IllegalStateException e) {
            // a closed case is terminal; say so rather than silently doing nothing
            throw new ResponseStatusException(org.springframework.http.HttpStatus.CONFLICT, e.getMessage());
        }
    }

    @GetMapping("/stats")
    public Map<String, Object> stats() {
        Map<CaseStatus, Long> byStatus = cases.countsByStatus();
        long total = byStatus.values().stream().mapToLong(Long::longValue).sum();
        Map<String, Long> lastHour = cases.verdictCountsLastHour();
        return Map.of(
                "byStatus", byStatus,
                "total", total,
                "last1h", Map.of(
                        "cases", lastHour.values().stream().mapToLong(Long::longValue).sum(),
                        "review", lastHour.getOrDefault("review", 0L),
                        "block", lastHour.getOrDefault("block", 0L)));
    }

    private static CaseStatus parseStatus(String status) {
        if (status == null || status.isBlank()) return null;
        try {
            return CaseStatus.valueOf(status.trim().toUpperCase());
        } catch (IllegalArgumentException e) {
            throw new ResponseStatusException(org.springframework.http.HttpStatus.BAD_REQUEST,
                    "unknown status '" + status + "', expected one of " + List.of(CaseStatus.values()));
        }
    }

    private static ResponseStatusException notFound(UUID caseId) {
        return new ResponseStatusException(org.springframework.http.HttpStatus.NOT_FOUND, "no case " + caseId);
    }
}
