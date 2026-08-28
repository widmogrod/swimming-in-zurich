# fastlane, and ONLY fastlane. It is here for one job: `xcrun altool` can upload a build but
# cannot submit it for review, and submitting means a sequence of App Store Connect API calls
# (create the version, attach the build, answer export compliance, create the submission).
# `upload_to_app_store` is that sequence, maintained by somebody else.
#
# NO Gemfile.lock, deliberately — see .gitignore. A lock records a resolution made on ONE Ruby,
# and the only Ruby available to author it here is Apple's system 2.6, which resolves gems the
# runner's 3.3 cannot install (`CFPropertyList 3.0.9 requires ruby < 3.2`). A lock that pins the
# wrong interpreter's answer is worse than no lock, so the version floor lives here instead and
# the runner resolves against the Ruby it will actually run.
source "https://rubygems.org"

gem "fastlane", "~> 2.230"
