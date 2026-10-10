package vn.vast.vasteq.user;

import java.security.*;
import java.util.*;
import javax.crypto.SecretKeyFactory;
import javax.crypto.spec.PBEKeySpec;
import jakarta.enterprise.context.ApplicationScoped;

@ApplicationScoped
public class PasswordHasher {
    private static final int ITERATIONS = 600_000;
    private final SecureRandom random = new SecureRandom();
    private static byte[] derive(String password, byte[] salt, int iterations) {
        PBEKeySpec spec = new PBEKeySpec(password.toCharArray(), salt, iterations, 256);
        try { return SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256").generateSecret(spec).getEncoded(); }
        catch (GeneralSecurityException e) { throw new IllegalStateException("Password hashing unavailable", e); }
        finally { spec.clearPassword(); }
    }
    public String hash(String password) {
        byte[] salt = new byte[16]; random.nextBytes(salt);
        var encoder = Base64.getEncoder().withoutPadding();
        return "pbkdf2-sha256$"+ITERATIONS+"$"+encoder.encodeToString(salt)+"$"+encoder.encodeToString(derive(password,salt,ITERATIONS));
    }
    public boolean verify(String password, String stored) {
        try {
            String[] parts = stored.split("\\$");
            if (parts.length != 4 || !parts[0].equals("pbkdf2-sha256")) return false;
            int iterations = Integer.parseInt(parts[1]);
            if (iterations < ITERATIONS || iterations > 2_000_000) return false;
            byte[] salt = Base64.getDecoder().decode(parts[2]);
            byte[] expected = Base64.getDecoder().decode(parts[3]);
            return salt.length == 16 && expected.length == 32 && MessageDigest.isEqual(expected,derive(password,salt,iterations));
        } catch (IllegalArgumentException e) { return false; }
    }
}
