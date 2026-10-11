# Infrastructure Excellence Roadmap for QA AI Dashboard Platform

> **Status (2026-10-11): a target plan written in July 2026, not a description of what runs.**
> None of the `infra/` deliverables below exist. What is true today: services log to stdout
> (the gateway writes one JSON line per request) and every service serves Prometheus `/metrics`;
> the monitoring stack is an opt-in compose profile (Prometheus, Alertmanager, exporters, alert rules, Grafana dashboards and
> its QEOS sign-in, ADR-027, `docs/superpowers/specs/2026-10-10-monitoring-design.md`). CI runs every test suite,
> container smoke tests and a full-stack gateway smoke (`.github/workflows/ci.yml`); CodeQL and
> Dependabot cover security scanning (2.2, in part); the gateway enforces per-IP rate limits (2.3,
> in part). No Loki, Jaeger, Istio, Vault, Kafka/schema registry, autoscaling, chaos tooling,
> feature flags, Hadolint or SBOMs. Production is one VM with Docker Compose behind Caddy
> (ADR-019); Kubernetes-based items wait on the blueprint's adoption triggers. Current state:
> README.md, TECHNICAL_SPECIFICATION.md, the blueprint banner. The file's original text ended in
> corrupted content after 4.4, which was removed on 2026-10-11.

This document outlines a comprehensive plan to address all infrastructure gaps identified in the platform assessment, following industry best practices for cloud-native, enterprise-grade applications.

## Executive Summary

The QA AI Dashboard Platform (now QEOS) has microservices foundations with idempotent uploads and retrying clients, and basic observability (stdout logging, Prometheus `/metrics`; no tracing). However, to achieve production-grade excellence, the platform requires significant enhancements in infrastructure, observability, security, and automation domains.

This roadmap provides a prioritized, actionable plan to address all 18 identified gaps, organized by implementation phases with clear deliverables, success criteria, and estimated effort.

## Phase 1: Foundation & Observability (Weeks 1-4)

### 1.1 Centralized Logging & Metrics Backend
**Gap**: Only the gateway logs JSON (the services write plain text) and nothing ships logs to a central store; metrics are exposed but there are no Grafana dashboards or alerting rules yet.

**Solution**: 
- Deploy Loki/Promtail/Grafana (Loki stack) for log aggregation
- Enhance Prometheus deployment with recording rules and alerting
- Create standardized Grafana dashboards for service-level and business metrics
- Implement structured logging enrichment with trace IDs and service metadata

**Deliverables**:
- `infra/logging/loki-stack/` - Helm chart for Loki stack
- `infra/monitoring/prometheus/` - Enhanced Prometheus configuration
- `infra/monitoring/grafana/dashboards/` - Service and business dashboards
- `infra/logging/logging-standard.md` - Logging format guidelines
- Updated services to emit structured logs with trace context

**Success Criteria**:
- All service logs aggregated in Loki with <5s latency
- Grafana dashboards showing RED metrics (Rate, Errors, Duration) for all services
- Alerting rules configured for critical SLO violations
- Documentation on log format and querying

### 1.2 Distributed Tracing Enhancement
**Gap**: No distributed tracing (the July text assumed a basic Jaeger setup; none exists).

**Solution**:
- Ensure 100% trace propagation across all service boundaries
- Add custom spans for business logic operations
- Implement trace sampling strategies for cost control
- Add trace-based alerting for latency anomalies

**Deliverables**:
- `infra/tracing/jaeger/` - Jaeger configuration
- `shared/lib/tracing/` - Enhanced tracing library with auto-instrumentation
- Tracing instrumentation guide for service owners

**Success Criteria**:
- End-to-end tracing for all user journeys
- <1% trace loss rate
- Ability to trace requests from ingress to database

### 1.3 Service Mesh Foundation
**Gap**: No service mesh for mTLS, traffic management, observability.

**Solution**:
- Implement Istio service mesh in evaluation mode
- Start with permissive mTLS, progress to strict
- Implement basic traffic policies (retries, timeouts, circuit breakers)
- Leverage built-in telemetry for enhanced observability

**Deliverables**:
- `infra/servicemesh/istio/` - Istio installation and configuration
- `infra/servicemesh/policies/` - Default traffic policies
- Service mesh onboarding guide

**Success Criteria**:
- mTLS encryption between all services
- Automatic mutual TLS for service-to-service communication
- Built-in retries, timeouts, and circuit breaking via Istio
- Enhanced telemetry without application code changes

## Phase 2: Security & Compliance (Weeks 5-8)

### 2.1 Secrets Management Implementation
**Gap**: Reliance on raw environment files; no integration with HashiCorp Vault/cloud secret managers.

**Solution**:
- Deploy HashiCorp Vault in production mode
- Implement Kubernetes CSI driver for secret injection
- Create secrets management policies and procedures
- Migrate all credentials from environment files to Vault

**Deliverables**:
- `infra/secrets/vault/` - Vault deployment configuration
- `infra/secrets/policies/` - Vault policies for different environments
- `infra/secrets/csi-driver/` - Kubernetes CSI driver configuration
- Secrets migration scripts and procedures

**Success Criteria**:
- No hardcoded secrets in repositories or configuration files
- Dynamic secret generation where possible
- Audit logging of all secret access
- Automatic secret rotation for supported secrets

### 2.2 Security Scanning Integration
**Gap**: No visible SAST/DAST, dependency-check, or container image scanning in CI.

**Solution**:
- Implement GitHub Actions security scanning workflows
- Integrate Trivy for container image scanning
- Integrate Semgrep for SAST
- Integrate OWASP Dependency-Check for vulnerability scanning
- Implement DAST scanning with OWASP ZAP in staging

**Deliverables**:
- `.github/workflows/security-scan.yml` - Comprehensive security workflow
- `infra/security/scanners/` - Scanner configurations and policies
- `SECURITY.md` - Security policy and vulnerability reporting procedure

**Success Criteria**:
- Automated security scanning on every pull request
- Blocking of merges for critical/high vulnerabilities
- Weekly dependency scanning with automated PR updates
- Container image scanning before deployment to any environment

### 2.3 API Security & Governance
**Gap**: No API gateway, developer portal, versioning policy, or contract testing.

**Solution**:
- Deploy Kong API Gateway (open source edition)
- Implement API versioning strategy (URI versioning: /v1/resource)
- Create developer portal with API documentation
- Implement contract testing with Pact for critical service interactions
- Add rate limiting, authentication, and request transformation at gateway

**Deliverables**:
- `infra/apigateway/kong/` - Kong deployment and configuration
- `infra/apigateway/policies/` - Rate limiting, auth, transformation policies
- `docs/api/` - API documentation portal
- `infra/testing/contract/` - Pact contract tests for service boundaries
- API governance documentation

**Success Criteria**:
- 100% of external traffic routed through API gateway
- Automated API documentation generation from OpenAPI specs
- Contract tests preventing breaking changes
- Rate protection and authentication for all external APIs

## Phase 3: Reliability & Scalability (Weeks 9-12)

### 3.1 Event Streaming & Schema Management
**Gap**: Kafka topics exist but no Schema Registry for versioning/compatibility.

**Solution**:
- Deploy Confluent Schema Registry (or Apicurio) for Kafka
- Implement schema validation for all event producers/consumers
- Establish schema evolution guidelines (backward/forward compatibility)
- Add schema validation to CI pipeline

**Deliverables**:
- `infra/eventing/schema-registry/` - Schema registry deployment
- `infra/eventing/schemas/` - Standardized event schemas
- `shared/lib/avro/` - Avro serialization utilities for events
- Event schema evolution guidelines

**Success Criteria**:
- All events validated against schema before publishing
- Backward and forward compatibility enforced
- Schema versioning visible in topic names or headers
- Automated schema compatibility checking in CI

### 3.2 Autoscaling Implementation
**Gap**: No HPA/VPA definitions or custom metrics-based scaling.

**Solution**:
- Implement Horizontal Pod Autoscaler based on CPU/memory and custom metrics
- Add Vertical Pod Autoscaler for resource optimization
- Implement custom metrics adapters for business metrics (queue depth, request rate)
- Configure cluster autoscaler for node-level scaling

**Deliverables**:
- `infra/autoscaling/hpa/` - HPA configurations for services
- `infra/autoscaling/vpa/` - VPA configurations
- `infra/autoscaling/custom-metrics/` - Custom metrics adapter configs
- Autoscaling policies and procedures documentation

**Success Criteria**:
- Services automatically scale based on load
- Resource optimization reducing wasted capacity
- Rapid response to traffic spikes
- Cost efficiency through right-sizing

### 3.3 Chaos Engineering Framework
**Gap**: No chaos engineering or fault injection experiments.

**Solution**:
- Implement Chaos Mesh or LitmusChaos for Kubernetes-native chaos engineering
- Define chaos experiments for network latency, pod failures, node drains
- Create game day procedures and runbooks
- Integrate chaos experiments into pre-release validation

**Deliverables**:
- `infra/chaos/chaos-mesh/` - Chaos Mesh installation and configuration
- `infra/chaos/experiments/` - Predefined chaos experiments
- `infra/chaos/runbooks/` - Game day procedures
- Chaos engineering maturity model

**Success Criteria**:
- Regular chaos experiments run in staging
- Measurable improvements in system resilience
- Documented procedures for incident response
- Chaos engineering integrated into release process

## Phase 4: Developer Experience & Automation (Weeks 13-16)

### 4.1 CI/CD Pipeline Implementation
**Gap**: Absent build, test, security scan, container image push, and deployment automation.

**Solution**:
- Implement GitHub Actions workflows for CI/CD
- Create standardized build, test, security, and deployment pipelines
- Implement blue/green deployment strategies
- Add automated rollback capabilities
- Implement environment promotion (dev → staging → prod)

**Deliverables**:
- `.github/workflows/ci-cd.yml` - Comprehensive CI/CD pipeline
- `infra/cicd/templates/` - Reusable workflow templates
- `infra/cicd/argo-cd/` - GitOps deployment with Argo CD (optional)
- Release management procedures

**Success Criteria**:
- Every commit to main triggers build, test, security scan
- Automated deployment to staging on successful pipeline completion
- Manual approval gates for production deployment
- Rollback capability within 5 minutes of bad deployment
- Zero-downtime deployments for stateless services

### 4.2 Configuration Management & Feature Flags
**Gap**: No feature-flag system or distributed config service.

**Solution**:
- Implement OpenFeature flag provider with a self-hosted flagd service
- Create centralized configuration service using Spring Cloud Config or Consul
- Implement feature flag lifecycle management (rollout, targeting, cleanup)
- Add feature flag evaluation SDK to all services

**Deliverables**:
- `infra/config/featureflags/` - Flagd deployment and configuration
- `infra/config/service/` - Configuration service implementation
- `shared/lib/config/` - Configuration client library
- `shared/lib/featureflags/` - Feature flag SDK
- Feature flag management UI (optional)

**Success Criteria**:
- Runtime configuration updates without redeployment
- Feature flags for safe rollouts and experimentation
- Centralized configuration management
- Audit trail for configuration changes

### 4.3 Service Discovery & Mesh
**Gap**: Services rely on static host/port configuration via environment variables.

**Solution**:
- Leverage Kubernetes internal DNS for service discovery
- Implement headless services for StatefulSets where needed
- Use service mesh for advanced traffic management (retries, timeouts, etc.)
- Deprecate hardcoded service references in favor of DNS/service mesh

**Deliverables**:
- `infra/servicemesh/discovery/` - Service discovery configuration
- Migration guide from environment variables to service discovery
- Updated service-to-service communication patterns

**Success Criteria**:
- No hardcoded IP addresses or ports in service configurations
- Services discover each other via DNS or service mesh
- Transparent service registration and discovery
- Network policies restricting unnecessary service communication

### 4.4 Build Artifact Standardization
**Gap**: No Buildpacks, Dockerfile linting (Hadolint), or SBOM generation.

**Solution**:
- Implement Hadolint for Dockerfile linting in CI
- Add SBOM generation using Syft or similar in build process
