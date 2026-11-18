import { Route, Routes } from "react-router-dom";
import NotFoundPanel from "@/components/NotFoundPanel";
import OfficeHome from "./Home";
import NewProgram from "./NewProgram";
import ProgramPage from "./ProgramPage";

/** Design Office (plan docs/plans/CHIEF_DESIGNER.md): /app/office, /app/office/new, /app/office/programs/:pid. */
export default function Office() {
  return (
    <Routes>
      <Route index element={<OfficeHome />} />
      <Route path="new" element={<NewProgram />} />
      <Route path="programs/:pid" element={<ProgramPage />} />
      <Route path="*" element={<NotFoundPanel />} />
    </Routes>
  );
}
