import { Link, useParams } from "react-router-dom";
import { useTitle } from "@/lib/title";
import { cx } from "@/lib/format";
import { Badge3D, Card3D } from "@/components/landing/site";

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
  const key = DOCS[doc] ? doc : "terms";
  const d = DOCS[key]!;
  useTitle(d.title);
  return (
    <main className="s-grid border-b border-ink/80">
      <div className="mx-auto grid max-w-[1240px] gap-10 px-4 py-14 sm:px-6 sm:py-20 lg:grid-cols-[220px_minmax(0,1fr)]">
        <nav aria-label="Legal documents" className="lg:sticky lg:top-24 lg:self-start">
          <div className="s-anno text-bp">Documents</div>
          <ul className="mt-3 border-t border-ink/70">
            {Object.entries(DOCS).map(([k, v], i) => (
              <li key={k}><Link to={"/legal/" + k} aria-current={k === key ? "page" : undefined}
                className={cx("flex min-h-[44px] items-center gap-3 border-b border-rule text-[15px]", k === key ? "font-semibold text-ink" : "text-ink2 hover:text-ink")}>
                <span className="s-anno text-bp">L.{i + 1}</span>{v.title}</Link></li>
            ))}
          </ul>
        </nav>
        <Card3D inner="p-6 sm:p-10">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-ink/70 pb-4">
            <Badge3D tone="hi">Draft · pending legal review</Badge3D>
            <span className="s-anno text-ink2">Rev 0 · not yet binding</span>
          </div>
          <h1 className="s-h2 mt-6 text-[34px] text-ink sm:text-[48px]">{d.title}</h1>
          <p className="mt-3 max-w-2xl text-[16px] leading-relaxed text-ink2">This document is a working draft and is not yet legally binding. Final terms will be published before general availability.</p>
          <div className="mt-10 max-w-[70ch] space-y-8">
            {d.sections.map(([h, b]) => (
              <section key={h} className="border-t border-rule pt-5">
                <h2 className="text-[18px] font-semibold text-ink" style={{ fontFamily: "inherit", fontStretch: "normal", letterSpacing: 0 }}>{h}</h2>
                <p className="mt-2 text-[16px] leading-relaxed text-ink2">{b}</p>
              </section>
            ))}
          </div>
        </Card3D>
      </div>
    </main>
  );
}
