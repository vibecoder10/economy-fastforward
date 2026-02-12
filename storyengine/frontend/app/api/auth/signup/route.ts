import { NextResponse } from "next/server";
import bcrypt from "bcryptjs";
import { prisma } from "@/lib/prisma";
import { ECONOMY_FASTFORWARD_PROFILE } from "@shared/constants";

export async function POST(request: Request) {
  try {
    const { name, email, password } = await request.json();

    if (!email || !password) {
      return NextResponse.json(
        { error: "Email and password are required" },
        { status: 400 }
      );
    }

    if (password.length < 8) {
      return NextResponse.json(
        { error: "Password must be at least 8 characters" },
        { status: 400 }
      );
    }

    // Check if user already exists
    const existingUser = await prisma.user.findUnique({
      where: { email },
    });

    if (existingUser) {
      return NextResponse.json(
        { error: "An account with this email already exists" },
        { status: 409 }
      );
    }

    const hashedPassword = await bcrypt.hash(password, 12);

    // Create user with default channel profile
    const user = await prisma.user.create({
      data: {
        name: name || null,
        email,
        hashedPassword,
        subscriptionTier: "taste",
        channelProfiles: {
          create: {
            name: ECONOMY_FASTFORWARD_PROFILE.name,
            isDefault: true,
            narrativeConfig: JSON.stringify(
              ECONOMY_FASTFORWARD_PROFILE.narrativeConfig
            ),
            visualConfig: JSON.stringify(
              ECONOMY_FASTFORWARD_PROFILE.visualConfig
            ),
            visualAnchors: JSON.stringify(
              ECONOMY_FASTFORWARD_PROFILE.visualAnchors
            ),
          },
        },
      },
    });

    return NextResponse.json({
      id: user.id,
      email: user.email,
      name: user.name,
    });
  } catch (error) {
    console.error("Signup error:", error);
    return NextResponse.json(
      { error: "Internal server error" },
      { status: 500 }
    );
  }
}
