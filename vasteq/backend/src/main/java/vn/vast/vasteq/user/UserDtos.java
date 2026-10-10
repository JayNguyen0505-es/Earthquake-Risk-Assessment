package vn.vast.vasteq.user;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Locale;
import jakarta.validation.constraints.*;

public final class UserDtos {
    private UserDtos() {}
    private static String email(String value) { return value == null ? null : value.strip().toLowerCase(Locale.ROOT); }
    private static String name(String value) { return value == null ? null : value.strip(); }
    public record Register(@NotBlank @Email @Size(max=254) String email,
                           @NotNull @Size(min=12,max=128) String password,
                           @NotBlank @Size(max=120) String displayName) {
        public Register { email=UserDtos.email(email); displayName=name(displayName); }
    }
    public record Login(@NotBlank @Email @Size(max=254) String email,
                        @NotNull @Size(min=1,max=128) String password) {
        public Login { email=UserDtos.email(email); }
    }
    public record Profile(@Email @Size(min=1,max=254) String email,
                          @Size(min=1,max=120) String displayName) {
        public Profile { email=UserDtos.email(email); displayName=name(displayName); }
    }
    public record PasswordChange(@NotNull @Size(min=1,max=128) String currentPassword,
                                 @NotNull @Size(min=12,max=128) String newPassword) {}
    public record AdminCreate(@NotBlank @Email @Size(max=254) String email,
                              @NotNull @Size(min=12,max=128) String password,
                              @NotBlank @Size(max=120) String displayName,
                              @Pattern(regexp="admin|user|guest") String role) {
        public AdminCreate { email=UserDtos.email(email); displayName=name(displayName); }
    }
    public record AdminUpdate(@Email @Size(min=1,max=254) String email,
                              @Size(min=1,max=120) String displayName,
                              @Pattern(regexp="admin|user|guest") String role, Boolean enabled) {
        public AdminUpdate { email=UserDtos.email(email); displayName=name(displayName); }
    }
    public record View(long id, String email, String displayName, String role, boolean enabled,
                       LocalDateTime createdAt, LocalDateTime updatedAt) {}
    public record Token(String accessToken, String tokenType, long expiresIn, View user) {}
    public record Page(List<View> items, long total, int offset, int limit) {}
}
