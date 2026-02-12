import Link from "next/link";

export default function LandingPage() {
  return (
    <div className="min-h-screen flex flex-col items-center justify-center px-6">
      <div className="max-w-2xl text-center space-y-8">
        <h1 className="text-5xl md:text-6xl font-bold tracking-tight">
          Story
          <span className="text-accent">Engine</span>
        </h1>

        <p className="text-xl text-text-secondary leading-relaxed max-w-lg mx-auto">
          Transform a simple video idea into a fully produced visual
          narrative&mdash;beat sheet, script, 120+ scene images, and selective
          animation.
        </p>

        <div className="flex flex-col sm:flex-row gap-4 justify-center pt-4">
          <Link
            href="/auth/signup"
            className="px-8 py-3 bg-accent hover:bg-accent-hover text-background font-semibold rounded-lg transition-colors"
          >
            Get Started
          </Link>
          <Link
            href="/auth/login"
            className="px-8 py-3 border border-border hover:border-border-hover text-text-primary font-semibold rounded-lg transition-colors"
          >
            Sign In
          </Link>
        </div>
      </div>

      <footer className="absolute bottom-8 text-text-tertiary text-sm">
        Story-first production engine for creators
      </footer>
    </div>
  );
}
