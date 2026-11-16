import { useParams } from "react-router-dom";
import { Badge } from "@/components/ui";

const DOCS: Record<string, { title: string; sections: [string, string][] }> = {
  terms: { title: "Terms of service", sections: [
    ["1. The service", "Formwright provides AI-assisted design tools that generate parametric CAD models and related outputs for professional users."],
    ["2. Your content", "You retain all rights to the designs, prompts and files you create or upload. You grant us only the rights needed to operate the service for you."],
    ["3. Engineering responsibility", "Outputs are design aids. They are not certified, validated or approved for manufacture. A qualified engineer must review every design before use, especially for safety-critical applications."],
    ["4. Plans, tokens and billing", "Subscriptions renew monthly until cancelled. Tokens meter AI usage; unused plan tokens follow the plan's allowance rules. Prices may change with notice."],
    ["5. Acceptable use", "No unlawful content, export-controlled data without authorization, attempts to break isolation or security, or resale without agreement."],
  ] },
  privacy: { title: "Privacy policy", sections: [
    ["What we collect", "Account details (name, email), workspace and billing records, usage events that power your checklist and product analytics, and the content you create."],
    ["How we use it", "To operate the service, bill you, support you, and improve the product. We do not sell personal data."],
    ["AI processing", "Prompts and design context are processed by our AI provider to generate results under commercial terms. Enterprise customers can request alternative processing arrangements."],
    ["Retention & deletion", "You can delete projects at any time. Account deletion removes your data subject to legal retention requirements."],
    ["Contact", "privacy@formwright.dev"],
  ] },
  aup: { title: "Acceptable use policy", sections: [
    ["Prohibited", "Weapons design in violation of law, export-controlled technical data without authorization, malware, abuse of the service or other users."],
    ["Enforcement", "We may suspend accounts that violate this policy and will notify you where lawful."],
  ] },
};

export default function Legal() {
  const { doc = "terms" } = useParams();
  const d = DOCS[doc] ?? DOCS.terms!;
  return (
    <main className="mx-auto max-w-3xl px-4 py-16 sm:px-6">
      <Badge tone="warning">Draft — pending legal review</Badge>
      <h1 className="mt-4 text-3xl font-semibold tracking-tight">{d.title}</h1>
      <p className="mt-2 text-sm text-muted">This document is a working draft and is not yet legally binding. Final terms will be published before general availability.</p>
      <div className="mt-10 space-y-8">
        {d.sections.map(([h, b]) => <section key={h}><h2 className="font-semibold">{h}</h2><p className="mt-2 leading-relaxed text-muted">{b}</p></section>)}
      </div>
    </main>
  );
}
