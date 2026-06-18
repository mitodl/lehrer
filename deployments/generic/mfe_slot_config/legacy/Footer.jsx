/**
 * Generic Open edX footer component — no operator customizations.
 *
 * This is a minimal footer for vanilla Open edX deployments. Replace this
 * file with your own Footer.jsx to customize the MFE footer for your operator.
 */

import React from "react";
import { Hyperlink, Image } from "@openedx/paragon";

const Footer = () => {
  return (
    <footer className="d-flex flex-column align-items-center py-3 px-4">
      <div className="d-flex gap-3 align-items-center mb-2">
        <Hyperlink destination="https://openedx.org">
          <Image
            width="120px"
            alt="Open edX"
            src="https://logos.openedx.org/open-edx-logo-tag.png"
          />
        </Hyperlink>
      </div>
      <div className="text-center x-small text-muted">
        {"edX and Open edX are registered trademarks of edX LLC."}
      </div>
    </footer>
  );
};

export default Footer;
