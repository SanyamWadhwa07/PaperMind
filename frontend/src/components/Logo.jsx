export default function Logo({ className = "w-8 h-8", type = "icon" }) {
  if (type === "full") {
    // Full logo with text
    return (
      <svg 
        className={className} 
        viewBox="0 0 200 60" 
        fill="none" 
        xmlns="http://www.w3.org/2000/svg"
      >
        {/* Icon part */}
        <g>
          {/* Brain outline */}
          <path 
            d="M24 10 C18 10 14 14 14 20 C14 22 14.5 23.5 15 25 C13 26 12 28 12 30 C12 33 14 35 16 36 C16 38 17 40 19 41 C19 43 20 45 22 46 C23 48 25 49 28 49 C30 49 32 48 33 47 C35 47 36 46 37 45 C38 44 39 42 39 40 C40 39 41 37 41 35 C42 34 43 32 43 30 C43 28 42 26 41 25 C42 23 43 21 43 19 C43 15 40 12 36 11 C34 10 30 9 24 10 Z" 
            fill="url(#gradient1)" 
            stroke="url(#gradient2)" 
            strokeWidth="1.5"
          />
          
          {/* Brain details - left hemisphere */}
          <path 
            d="M18 22 Q20 24 18 26 Q16 28 18 30 Q20 32 18 34" 
            stroke="white" 
            strokeWidth="1.5" 
            strokeLinecap="round" 
            fill="none" 
            opacity="0.6"
          />
          
          {/* Brain details - right hemisphere */}
          <path 
            d="M30 22 Q28 24 30 26 Q32 28 30 30 Q28 32 30 34" 
            stroke="white" 
            strokeWidth="1.5" 
            strokeLinecap="round" 
            fill="none" 
            opacity="0.6"
          />
          
          {/* Center line */}
          <line x1="24" y1="15" x2="24" y2="42" stroke="white" strokeWidth="1" opacity="0.3" strokeDasharray="2,2" />
          
          {/* AI Sparkles */}
          <path d="M12 15 L13 17 L12 19 L11 17 Z" fill="#D9A86C" opacity="0.9">
            <animateTransform
              attributeName="transform"
              type="scale"
              values="1;1.2;1"
              dur="2s"
              repeatCount="indefinite"
            />
          </path>
          <path d="M38 12 L39.5 14 L38 16 L36.5 14 Z" fill="#D9A86C" opacity="0.9">
            <animateTransform
              attributeName="transform"
              type="scale"
              values="1;1.3;1"
              dur="2.5s"
              repeatCount="indefinite"
            />
          </path>
          <path d="M36 44 L37 45.5 L36 47 L35 45.5 Z" fill="#D9A86C" opacity="0.8">
            <animateTransform
              attributeName="transform"
              type="scale"
              values="1;1.15;1"
              dur="3s"
              repeatCount="indefinite"
            />
          </path>
        </g>
        
        {/* Text part */}
        <text x="55" y="32" fontFamily="Arial, sans-serif" fontSize="24" fontWeight="bold" fill="url(#textGradient)">
          PaperMind
        </text>
        <text x="55" y="48" fontFamily="Arial, sans-serif" fontSize="11" fontWeight="500" fill="currentColor" opacity="0.7">
          AI Research Assistant
        </text>
        
        {/* Gradients */}
        <defs>
          <linearGradient id="gradient1" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#00988F" />
            <stop offset="100%" stopColor="#00C4B8" />
          </linearGradient>
          <linearGradient id="gradient2" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#00A7A0" />
            <stop offset="100%" stopColor="#00E5D6" />
          </linearGradient>
          <linearGradient id="textGradient" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="#00988F" />
            <stop offset="100%" stopColor="#C4935F" />
          </linearGradient>
        </defs>
      </svg>
    )
  }
  
  // Icon only (default)
  return (
    <svg 
      className={className} 
      viewBox="0 0 48 60" 
      fill="none" 
      xmlns="http://www.w3.org/2000/svg"
    >
      {/* Brain outline */}
      <path 
        d="M24 10 C18 10 14 14 14 20 C14 22 14.5 23.5 15 25 C13 26 12 28 12 30 C12 33 14 35 16 36 C16 38 17 40 19 41 C19 43 20 45 22 46 C23 48 25 49 28 49 C30 49 32 48 33 47 C35 47 36 46 37 45 C38 44 39 42 39 40 C40 39 41 37 41 35 C42 34 43 32 43 30 C43 28 42 26 41 25 C42 23 43 21 43 19 C43 15 40 12 36 11 C34 10 30 9 24 10 Z" 
        fill="url(#gradient1)" 
        stroke="url(#gradient2)" 
        strokeWidth="1.5"
      />
      
      {/* Brain details - left hemisphere */}
      <path 
        d="M18 22 Q20 24 18 26 Q16 28 18 30 Q20 32 18 34" 
        stroke="white" 
        strokeWidth="1.5" 
        strokeLinecap="round" 
        fill="none" 
        opacity="0.6"
      />
      
      {/* Brain details - right hemisphere */}
      <path 
        d="M30 22 Q28 24 30 26 Q32 28 30 30 Q28 32 30 34" 
        stroke="white" 
        strokeWidth="1.5" 
        strokeLinecap="round" 
        fill="none" 
        opacity="0.6"
      />
      
      {/* Center line */}
      <line x1="24" y1="15" x2="24" y2="42" stroke="white" strokeWidth="1" opacity="0.3" strokeDasharray="2,2" />
      
      {/* AI Sparkles with animation */}
      <path d="M12 15 L13 17 L12 19 L11 17 Z" fill="white" opacity="0.9">
        <animateTransform
          attributeName="transform"
          type="scale"
          values="1;1.2;1"
          dur="2s"
          repeatCount="indefinite"
        />
      </path>
      <path d="M38 12 L39.5 14 L38 16 L36.5 14 Z" fill="white" opacity="0.9">
        <animateTransform
          attributeName="transform"
          type="scale"
          values="1;1.3;1"
          dur="2.5s"
          repeatCount="indefinite"
        />
      </path>
      <path d="M36 44 L37 45.5 L36 47 L35 45.5 Z" fill="white" opacity="0.8">
        <animateTransform
          attributeName="transform"
          type="scale"
          values="1;1.15;1"
          dur="3s"
          repeatCount="indefinite"
        />
      </path>
      
      {/* Gradients */}
      <defs>
        <linearGradient id="gradient1" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#00988F" />
          <stop offset="100%" stopColor="#00C4B8" />
        </linearGradient>
        <linearGradient id="gradient2" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#00A7A0" />
          <stop offset="100%" stopColor="#00E5D6" />
        </linearGradient>
      </defs>
    </svg>
  )
}
